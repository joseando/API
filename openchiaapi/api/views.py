import os
import yaml

from blspy import AugSchemeMPL, G1Element, G2Element
from chia.pools.pool_wallet_info import PoolState
from chia.protocols.pool_protocol import validate_authentication_token, AuthenticationPayload
from chia.util.bech32m import decode_puzzle_hash
from chia.util.byte_types import hexstr_to_bytes
from chia.util.hash import std_hash
from chia.util.ints import uint64
from datetime import datetime, timedelta
from decimal import Decimal
from django.db.models import Sum
from django_filters.rest_framework import DjangoFilterBackend
from django_filters import rest_framework as django_filters
from drf_yasg import openapi
from drf_yasg.utils import swagger_auto_schema
from rest_framework import filters, mixins, serializers, viewsets
from rest_framework.exceptions import NotAuthenticated, NotFound
from rest_framework.views import APIView
from rest_framework.response import Response

from .models import Block, GlobalInfo, Launcher, Partial, Payout, PayoutAddress, Space
from .serializers import (
    BlockSerializer,
    LauncherSerializer,
    LauncherUpdateSerializer,
    LoginSerializer,
    PartialSerializer,
    PayoutSerializer,
    PayoutAddressSerializer,
    StatsSerializer,
    SpaceSerializer,
    XCHScanStatsSerializer,
)
from .utils import (
    get_pool_info, estimated_time_to_win,
)
from referral.utils import update_referral


def get_pool_target_address():
    cfg_path = os.environ.get('POOL_CONFIG_PATH') or ''
    if not os.path.exists(cfg_path):
        raise ValueError('POOL_CONFIG_PATH does not exist.')
    with open(cfg_path, 'r') as f:
        cfg = yaml.safe_load(f.read())
    return cfg['wallets'][0]['address']


POOL_TARGET_ADDRESS = get_pool_target_address()


class BlockViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = Block.objects.all()
    serializer_class = BlockSerializer
    filterset_fields = ['farmed_by', 'payout']
    ordering_fields = ['confirmed_block_index', 'payout']
    ordering = ['-confirmed_block_index']


class LauncherViewSet(
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.UpdateModelMixin,
    viewsets.GenericViewSet,
):
    queryset = Launcher.objects.all()
    filter_backends = [filters.SearchFilter, DjangoFilterBackend, filters.OrderingFilter]
    filterset_fields = ['difficulty', 'launcher_id', 'name', 'is_pool_member']
    search_fields = ['launcher_id', 'name']
    ordering_fields = ['points', 'difficulty']
    ordering = ['-points']

    def get_serializer_context(self):
        context = super().get_serializer_context()
        context['total_points'] = Launcher.objects.filter(is_pool_member=True).aggregate(
            total=Sum('points')
        )['total']
        return context

    def get_serializer_class(self, *args, **kwargs):
        if self.request.method == 'PUT':
            return LauncherUpdateSerializer
        return LauncherSerializer

    def update(self, request, pk):
        launcher_id = request.session.get('launcher_id')
        if not launcher_id or launcher_id != pk:
            raise NotAuthenticated()
        launcher = Launcher.objects.filter(launcher_id=pk)
        if not launcher.exists():
            raise NotFound()
        launcher = launcher[0]
        s = LauncherUpdateSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        launcher.name = s.validated_data['name']
        if 'email' in s.validated_data:
            launcher.email = s.validated_data['email']
        if 'notify_missing_partials_hours' in s.validated_data:
            launcher.notify_missing_partials_hours = s.validated_data['notify_missing_partials_hours']

        try:
            update_referral(launcher, s.validated_data.get('referrer') or None)
        except ValueError as e:
            raise serializers.ValidationError({'referrer': str(e)})

        launcher.save()
        return Response(s.validated_data)


class StatsView(APIView):

    @swagger_auto_schema(responses={200: StatsSerializer(many=False)})
    def get(self, request, format=None):
        coinrecord = Block.objects.order_by('-confirmed_block_index')
        farmers = Launcher.objects.filter(is_pool_member=True).count()
        pool_info = get_pool_info()
        try:
            size = Space.objects.latest('id').size
        except Space.DoesNotExist:
            size = 0

        globalinfo = GlobalInfo.load()
        minutes_to_win = estimated_time_to_win(
            size, int(globalinfo.blockchain_space), globalinfo.blockchain_avg_block_time,
        )
        pi = StatsSerializer(data={
            'fee': Decimal(pool_info['fee']),
            'farmers': farmers,
            'rewards_amount': coinrecord.aggregate(total=Sum('amount'))['total'],
            'rewards_blocks': coinrecord.count(),
            'pool_space': size,
            'estimate_win': minutes_to_win,
            'blockchain_height': globalinfo.blockchain_height,
            'blockchain_space': int(globalinfo.blockchain_space),
            'reward_system': 'PPLNS',
            'last_rewards': [{
                'date': datetime.utcfromtimestamp(i.timestamp),
                'height': i.confirmed_block_index,
            } for i in coinrecord[:10]],
            'xch_current_price': globalinfo.xch_current_price,
        })
        pi.is_valid()
        return Response(pi.data)


class XCHScanStatsView(APIView):

    @swagger_auto_schema(responses={200: XCHScanStatsSerializer(many=False)})
    def get(self, request, format=None):
        coinrecord = Block.objects.order_by('-confirmed_block_index')
        farmers = Launcher.objects.filter(is_pool_member=True).count()
        pool_info = get_pool_info()
        try:
            size = Space.objects.latest('id').size
        except Space.DoesNotExist:
            size = 0

        pi = XCHScanStatsSerializer(data={
            'poolInfo': {
                'puzzle_hash': '0x' + decode_puzzle_hash(POOL_TARGET_ADDRESS).hex(),
                'fee': Decimal(pool_info['fee']),
                'minPay': 0,
            },
            'farmers': farmers,
            'capacityBytes': size,
            'farmedBlocks': [{
                'time': i.timestamp,
                'height': i.confirmed_block_index,
            } for i in coinrecord[:10]],
        })
        pi.is_valid()
        return Response(pi.data)


class PartialFilter(django_filters.FilterSet):
    min_timestamp = django_filters.NumberFilter(field_name='timestamp', lookup_expr='gte')

    class Meta:
        model = Partial
        fields = ['launcher', 'timestamp']


class LoginView(APIView):
    """
    Login using parameters from chia plotnft.
    """

    @swagger_auto_schema(request_body=LoginSerializer)
    def post(self, request):
        s = LoginSerializer(data=request.data)
        s.is_valid(raise_exception=True)

        launcher_id = hexstr_to_bytes(s.validated_data["launcher_id"])
        authentication_token = uint64(s.validated_data["authentication_token"])
        if not validate_authentication_token(authentication_token, 10):
            raise NotAuthenticated(detail='Invalid authentication_token')

        launcher = Launcher.objects.filter(launcher_id=s.validated_data["launcher_id"])
        if not launcher.exists():
            raise NotFound()
        launcher = launcher[0]

        signature = G2Element.from_bytes(hexstr_to_bytes(s.validated_data["signature"]))
        message = std_hash(
            AuthenticationPayload(
                "get_login",
                launcher_id,
                PoolState.from_bytes(launcher.singleton_tip_state).target_puzzle_hash,
                authentication_token,
            )
        )
        if not AugSchemeMPL.verify(
            G1Element.from_bytes(bytes.fromhex(launcher.authentication_public_key)),
            message,
            signature
        ):
            raise NotAuthenticated(
                detail=f"Failed to verify signature {signature} for launcher_id {launcher_id.hex()}."
            )
        request.session['launcher_id'] = s.validated_data['launcher_id']
        return Response(True)


class LoggedInView(APIView):
    """
    Get the logged in launcher id.
    """

    @swagger_auto_schema(response_body=LoginSerializer)
    def get(self, request):
        return Response({
            'launcher_id': request.session.get('launcher_id'),
        })


class PartialViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = Partial.objects.all()
    serializer_class = PartialSerializer
    filterset_fields = ['launcher', 'timestamp', 'min_timestamp']
    filterset_class = PartialFilter
    ordering_fields = ['timestamp']
    ordering = ['-timestamp']


class PayoutViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = Payout.objects.all()
    serializer_class = PayoutSerializer
    ordering_fields = ['datetime']
    ordering = ['-datetime']


class PayoutAddressViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = PayoutAddress.objects.all()
    serializer_class = PayoutAddressSerializer
    filterset_fields = ['payout', 'puzzle_hash', 'launcher']
    ordering_fields = ['payout', 'launcher', 'confirmed_block_index']
    ordering = ['-payout']


class SpaceView(APIView):
    DEFAULT_DAYS = 30
    days_param = openapi.Parameter(
        'days',
        openapi.IN_QUERY,
        description=f'Number of days (default: {DEFAULT_DAYS})',
        type=openapi.TYPE_INTEGER,
    )

    @swagger_auto_schema(
        manual_parameters=[days_param],
        responses={200: SpaceSerializer(many=True)}
    )
    def get(self, request, format=None):
        days = self.request.query_params.get('days') or self.DEFAULT_DAYS
        size = Space.objects.filter(
            date__gte=datetime.now() - timedelta(days=int(days))
        ).order_by('date')
        return Response([{'date': i.date, 'size': i.size} for i in size])
